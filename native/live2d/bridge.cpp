// SomniLoop's thin C ABI over the official Cubism Native Framework.
// All calls run on the Qt GUI thread with its OpenGL context current.
#include <GL/glew.h>
#include <CubismFramework.hpp>
#include <CubismModelSettingJson.hpp>
#include <ICubismAllocator.hpp>
#include <Id/CubismIdManager.hpp>
#include <Model/CubismUserModel.hpp>
#include <Model/CubismModel.hpp>
#include <Motion/CubismMotion.hpp>
#include <Motion/CubismMotionManager.hpp>
#include <Motion/CubismExpressionMotionManager.hpp>
#include <Effect/CubismBreath.hpp>
#include <Effect/CubismEyeBlink.hpp>
#include <Effect/CubismPose.hpp>
#include <Physics/CubismPhysics.hpp>
#include <Math/CubismModelMatrix.hpp>
#include <Math/CubismTargetPoint.hpp>
#include <Rendering/OpenGL/CubismRenderer_OpenGLES2.hpp>
#include <algorithm>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <map>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

using namespace Live2D::Cubism::Framework;
namespace fs = std::filesystem;

namespace {
class Allocator final : public ICubismAllocator {
public:
    void* Allocate(csmSizeType n) override { return std::malloc(n); }
    void Deallocate(void* p) override { std::free(p); }
    void* AllocateAligned(csmSizeType n, csmUint32 alignment) override {
        void* p = nullptr;
        return posix_memalign(&p, std::max<size_t>(alignment, sizeof(void*)), n) == 0 ? p : nullptr;
    }
    void DeallocateAligned(void* p) override { std::free(p); }
};
Allocator allocator;
thread_local std::string lastError;
bool frameworkStarted = false;
CubismFramework::Option options{};
fs::path shaderRoot;

std::vector<csmByte> readFile(const fs::path& path) {
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file || file.tellg() <= 0 || file.tellg() > 64 * 1024 * 1024)
        throw std::runtime_error("Missing, empty or oversized Live2D resource: " + path.string());
    std::vector<csmByte> bytes(static_cast<size_t>(file.tellg()));
    file.seekg(0);
    if (!file.read(reinterpret_cast<char*>(bytes.data()), bytes.size()))
        throw std::runtime_error("Cannot read Live2D resource: " + path.string());
    return bytes;
}

csmByte* loadShader(const std::string path, csmSizeInt* size) {
    const auto bytes = readFile(shaderRoot / fs::path(path).filename());
    *size = static_cast<csmSizeInt>(bytes.size());
    auto* result = new csmByte[bytes.size()];
    std::copy(bytes.begin(), bytes.end(), result);
    return result;
}

class Character final : public CubismUserModel {
public:
    std::unique_ptr<CubismModelSettingJson> settings;
    std::map<std::string, std::vector<ACubismMotion*>> motions;
    std::map<std::string, ACubismMotion*> expressions;
    std::map<std::string, CubismIdHandle> ids;
    std::map<std::string, float> overrides;
    std::vector<GLuint> textures;
    std::map<std::string, std::vector<int>> partDrawables;
    std::string idleGroup;
    std::string activeGroup;
    bool idle = true;

    ~Character() override {
        _motionManager->StopAllMotions();
        _expressionManager->StopAllMotions();
        for (auto& group : motions) for (auto* motion : group.second) ACubismMotion::Delete(motion);
        for (auto& expression : expressions) ACubismMotion::Delete(expression.second);
        if (!textures.empty()) glDeleteTextures(textures.size(), textures.data());
    }

    void load(const char* filename) {
        const auto root = fs::path(filename).parent_path();
        auto bytes = readFile(filename);
        settings = std::make_unique<CubismModelSettingJson>(bytes.data(), bytes.size());
        bytes = readFile(root / settings->GetModelFileName());
        LoadModel(bytes.data(), bytes.size(), true);
        if (!_model) throw std::runtime_error("Cubism rejected the MOC3 model");
        const auto* parents = _model->GetPartParentPartIndices();
        for (int drawable = 0; drawable < _model->GetDrawableCount(); ++drawable) {
            int part = _model->GetDrawableParentPartIndex(drawable);
            for (int depth = 0; part >= 0 && part < _model->GetPartCount()
                 && depth < _model->GetPartCount(); ++depth) {
                partDrawables[_model->GetPartId(part)->GetString().GetRawString()].push_back(drawable);
                part = parents[part];
            }
        }
        for (int i = 0; i < _model->GetParameterCount(); ++i) {
            auto id = _model->GetParameterId(i);
            ids.emplace(id->GetString().GetRawString(), id);
        }
        if (*settings->GetPhysicsFileName()) {
            bytes = readFile(root / settings->GetPhysicsFileName());
            LoadPhysics(bytes.data(), bytes.size());
            if (!_physics) throw std::runtime_error("Invalid physics definition");
        }
        if (*settings->GetPoseFileName()) {
            bytes = readFile(root / settings->GetPoseFileName());
            LoadPose(bytes.data(), bytes.size());
        }
        if (*settings->GetUserDataFile()) {
            bytes = readFile(root / settings->GetUserDataFile());
            LoadUserData(bytes.data(), bytes.size());
        }
        _eyeBlink = CubismEyeBlink::Create(settings.get());
        _eyeBlink->SetBlinkingInterval(4.0f);
        _breath = CubismBreath::Create();
        csmVector<CubismBreath::BreathParameterData> breath;
        for (const char* key : {"PARAM_BREATH", "ParamBreath"}) {
            if (ids.count(key)) breath.PushBack({ids.at(key), 0.5f, 0.5f, 3.5f, 1.0f});
        }
        _breath->SetParameters(breath);
        csmVector<CubismIdHandle> eyes, lips;
        for (int i = 0; i < settings->GetEyeBlinkParameterCount(); ++i)
            eyes.PushBack(settings->GetEyeBlinkParameterId(i));
        for (int i = 0; i < settings->GetLipSyncParameterCount(); ++i)
            lips.PushBack(settings->GetLipSyncParameterId(i));
        for (int g = 0; g < settings->GetMotionGroupCount(); ++g) {
            const auto* group = settings->GetMotionGroupName(g);
            auto& entries = motions[group];
            if (std::string(group) == "Idle") idleGroup = group;
            for (int i = 0; i < settings->GetMotionCount(group); ++i) {
                bytes = readFile(root / settings->GetMotionFileName(group, i));
                auto* motion = LoadMotion(bytes.data(), bytes.size(), group, nullptr, nullptr, settings.get(), group, i, true);
                if (!motion) throw std::runtime_error("Invalid motion definition");
                auto* concrete = static_cast<CubismMotion*>(motion);
                concrete->SetEffectIds(eyes, lips);
                concrete->SetLoop(false);
                entries.push_back(motion);
            }
        }
        for (int i = 0; i < settings->GetExpressionCount(); ++i) {
            const auto* name = settings->GetExpressionName(i);
            bytes = readFile(root / settings->GetExpressionFileName(i));
            auto* expression = LoadExpression(bytes.data(), bytes.size(), name);
            if (!expression) throw std::runtime_error("Invalid expression definition");
            expressions.emplace(name, expression);
        }
        csmMap<csmString, csmFloat32> layout;
        settings->GetLayoutMap(layout);
        _modelMatrix->SetupFromLayout(layout);
        _model->SaveParameters();
        CreateRenderer();
        GetRenderer<Rendering::CubismRenderer_OpenGLES2>()->IsPremultipliedAlpha(false);
        textures.resize(settings->GetTextureCount(), 0);
    }

    void motion(const std::string& group, int index) {
        auto it = motions.find(group);
        if (it == motions.end() || index < 0 || index >= static_cast<int>(it->second.size()))
            throw std::runtime_error("Unknown motion group/index");
        _motionManager->StartMotionPriority(it->second[index], false, 3);
        activeGroup = group;
    }

    void setIdle(bool enabled) {
        idle = enabled;
        if (!idle && activeGroup == idleGroup) {
            _motionManager->StopAllMotions();
            activeGroup.clear();
        }
    }

    void expression(const std::string& name) {
        _expressionManager->StopAllMotions();
        if (name.empty()) return;
        auto it = expressions.find(name);
        if (it == expressions.end()) throw std::runtime_error("Unknown expression name");
        _expressionManager->StartMotionPriority(it->second, false, 3);
    }

    void add(const char* id, float value) {
        if (ids.count(id)) _model->AddParameterValue(ids.at(id), value);
    }

    CubismMatrix44 projection(int width, int height) {
        CubismMatrix44 result;
        result.Scale(0.95f * height / width, 0.95f);
        result.MultiplyByMatrix(_modelMatrix);
        return result;
    }

    void partBounds(const char* part, int width, int height, float* bounds) {
        auto found = partDrawables.find(part);
        if (found == partDrawables.end() || width <= 0 || height <= 0)
            throw std::runtime_error("Unknown or unavailable Live2D hit part");
        auto matrix = projection(width, height);
        bounds[0] = bounds[1] = std::numeric_limits<float>::infinity();
        bounds[2] = bounds[3] = -std::numeric_limits<float>::infinity();
        for (int drawable : found->second) {
            if (_model->GetDrawableOpacity(drawable) <= 0.01f) continue;
            const auto* vertices = _model->GetDrawableVertexPositions(drawable);
            for (int i = 0; i < _model->GetDrawableVertexCount(drawable); ++i) {
                const float x = (matrix.TransformX(vertices[i].X) + 1) * 0.5f;
                const float y = (1 - matrix.TransformY(vertices[i].Y)) * 0.5f;
                bounds[0] = std::min(bounds[0], x); bounds[1] = std::min(bounds[1], y);
                bounds[2] = std::max(bounds[2], x); bounds[3] = std::max(bounds[3], y);
            }
        }
        if (bounds[2] <= bounds[0] || bounds[3] <= bounds[1])
            throw std::runtime_error("Live2D hit part has no visible geometry");
    }

    void draw(float dt, int width, int height, float opacity) {
        dt = std::clamp(dt, 0.0f, 0.1f);
        _model->LoadParameters();
        if (idle && _motionManager->IsFinished() && !idleGroup.empty()) motion(idleGroup, 0);
        _motionManager->UpdateMotion(_model, dt);
        _model->SaveParameters();
        // Blink independently of idle clips, before expressions that may close the eyes.
        _eyeBlink->UpdateParameters(_model, dt);
        _expressionManager->UpdateMotion(_model, dt);
        _dragManager->Update(dt);
        const float x = _dragManager->GetX(), y = _dragManager->GetY();
        add("PARAM_ANGLE_X", x * 12); add("PARAM_ANGLE_Y", y * 8);
        add("PARAM_BODY_ANGLE_X", x * 3);
        add("PARAM_EYE_BALL_X", x * 0.7f); add("PARAM_EYE_BALL_Y", y * 0.7f);
        _breath->UpdateParameters(_model, dt);
        if (_physics) _physics->Evaluate(_model, dt);
        if (_pose) _pose->UpdateParameters(_model, dt);
        for (auto& entry : overrides) _model->SetParameterValue(ids.at(entry.first), entry.second);
        _model->Update();
        glViewport(0, 0, width, height);
        glDisable(GL_SCISSOR_TEST);
        glClearColor(0, 0, 0, 0);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
        auto transform = projection(width, height);
        auto* renderer = GetRenderer<Rendering::CubismRenderer_OpenGLES2>();
        renderer->SetMvpMatrix(&transform);
        renderer->SetModelColor(1, 1, 1, opacity);
        renderer->DrawModel();
        if (glGetError() != GL_NO_ERROR)
            throw std::runtime_error("Cubism OpenGL drawing failed");
    }

    float parameter(const char* id) {
        if (!ids.count(id)) throw std::runtime_error("Unknown parameter ID");
        return _model->GetParameterValue(ids.at(id));
    }
};

template<class F> int checked(F operation) {
    try { operation(); lastError.clear(); return 1; }
    catch (const std::exception& e) { lastError = e.what(); return 0; }
    catch (...) { lastError = "Unexpected native Live2D failure"; return 0; }
}
}

extern "C" {
const char* sl_error() { return lastError.c_str(); }
void* sl_create(const char* path, const char* shaders) {
    Character* model = nullptr;
    bool acquired = false;
    checked([&] {
        if (frameworkStarted) throw std::runtime_error("Only one Live2D renderer may own this bridge at a time");
        glewExperimental = GL_TRUE;
        const auto code = glewInit();
        // EGL contexts can report missing GLX although the OpenGL entry points loaded.
        if (code != GLEW_OK && !GLEW_VERSION_2_0) throw std::runtime_error("OpenGL 2.0 initialization failed");
        while (glGetError() != GL_NO_ERROR) {}
        shaderRoot = fs::path(shaders);
        options.LoadFileFunction = loadShader;
        options.ReleaseBytesFunction = [](csmByte* bytes) { delete[] bytes; };
        options.LoggingLevel = CubismFramework::Option::LogLevel_Off;
        if (!CubismFramework::StartUp(&allocator, &options)) throw std::runtime_error("Cubism startup failed");
        CubismFramework::Initialize();
        frameworkStarted = true;
        acquired = true;
        auto owned = std::make_unique<Character>();
        owned->load(path);
        model = owned.release();
    });
    if (!model && acquired) {
        CubismFramework::Dispose(); CubismFramework::CleanUp(); frameworkStarted = false;
    }
    return model;
}
int sl_texture(void* handle, int index, int width, int height, const unsigned char* rgba) {
    return checked([&] {
        auto* m = static_cast<Character*>(handle);
        if (index < 0 || index >= static_cast<int>(m->textures.size())) throw std::runtime_error("Invalid texture slot");
        glGenTextures(1, &m->textures[index]);
        glBindTexture(GL_TEXTURE_2D, m->textures[index]);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
        m->GetRenderer<Rendering::CubismRenderer_OpenGLES2>()->BindTexture(index, m->textures[index]);
        if (glGetError() != GL_NO_ERROR) throw std::runtime_error("OpenGL texture upload failed");
    });
}
int sl_draw(void* h, float dt, int w, int height, float opacity) {
    return checked([&] { static_cast<Character*>(h)->draw(dt, w, height, opacity); });
}
int sl_motion(void* h, const char* group, int index) {
    return checked([&] { static_cast<Character*>(h)->motion(group, index); });
}
int sl_expression(void* h, const char* name) {
    return checked([&] { static_cast<Character*>(h)->expression(name); });
}
int sl_parameter(void* h, const char* id, float value) {
    return checked([&] {
        auto* m = static_cast<Character*>(h);
        m->parameter(id);
        m->overrides[id] = value;
    });
}
int sl_get_parameter(void* h, const char* id, float* value) {
    return checked([&] { *value = static_cast<Character*>(h)->parameter(id); });
}
int sl_part_bounds(void* h, const char* part, int width, int height, float* bounds) {
    return checked([&] { static_cast<Character*>(h)->partBounds(part, width, height, bounds); });
}
void sl_look(void* h, float x, float y) { static_cast<Character*>(h)->SetDragging(x, y); }
void sl_idle(void* h, int enabled) { static_cast<Character*>(h)->setIdle(enabled != 0); }
const char* sl_motion_group(void* h) { return static_cast<Character*>(h)->activeGroup.c_str(); }
void sl_destroy(void* h) {
    if (!h) return;
    delete static_cast<Character*>(h);
    Rendering::CubismRenderer::StaticRelease();
    CubismFramework::Dispose(); CubismFramework::CleanUp(); frameworkStarted = false;
}
}
